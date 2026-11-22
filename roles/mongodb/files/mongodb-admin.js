/* No secrets in this file or command arguments. Run locally over verified TLS. */
const env = process.env;
const admin = db.getSiblingDB('admin');
const expected = JSON.parse(env.MONGODB_MEMBERS).map(m => ({_id: m.id, host: m.host})).sort((a,b) => a._id-b._id);
const action = env.MONGODB_ACTION;
let changed = false;
function requireValue(condition, message) { if (!condition) throw new Error(message); }
function command(database, value) {
  const result = database.runCommand(value);
  if (result.ok !== 1) { const error = new Error(result.errmsg || 'MongoDB command failed'); error.code = result.code; throw error; }
  return result;
}
function memberIdentity(members, idKey, hostKey) {
  return members.map(m => ({_id: m[idKey], host: m[hostKey]})).sort((a,b) => a._id-b._id);
}
function identity(status) {
  requireValue(status.set === env.MONGODB_SET, 'Unexpected replica-set name');
  requireValue(JSON.stringify(memberIdentity(status.members, '_id', 'name')) === JSON.stringify(expected), 'Unexpected replica-set membership');
}
function status() {
  const s = command(admin, {replSetGetStatus: 1});
  identity(s);
  return s;
}
function healthy() {
  const s = status();
  requireValue(s.members.length === 3 && s.members.every(m => m.health === 1 && [1,2].includes(m.state)), 'Every member must be healthy PRIMARY or SECONDARY');
  requireValue(s.members.filter(m => m.state === 1).length === 1, 'Exactly one primary is required');
  // Refuse to roll a badly lagging replica even when its heartbeat is healthy.
  const times = s.members.map(m => new Date(m.optimeDate).getTime());
  requireValue(times.every(Number.isFinite) && Math.max(...times)-Math.min(...times) <= 10000, 'Replication lag exceeds 10 seconds');
  return s;
}
function secureOptions(options) {
  requireValue(options.security && options.security.authorization === 'enabled' && options.security.clusterAuthMode === 'keyFile' && options.security.keyFile === '/etc/mongodb-krisx/keyfile', 'Running server authentication differs');
  requireValue(options.security.transitionToAuth !== true, 'Transitional authentication is unsafe');
  requireValue(options.net && options.net.tls && options.net.tls.mode === 'requireTLS', 'Running server does not require TLS');
  requireValue(options.net.tls.allowInvalidCertificates !== true && options.net.tls.allowInvalidHostnames !== true, 'TLS peer validation is relaxed');
  requireValue(options.replication && options.replication.replSetName === env.MONGODB_SET, 'Running server replica-set name differs');
}
function verifyConfig() {
  secureOptions(command(admin, {getCmdLineOpts: 1}).parsed);
  const c = command(admin, {replSetGetConfig: 1}).config;
  requireValue(c._id === env.MONGODB_SET && JSON.stringify(memberIdentity(c.members, '_id','host')) === JSON.stringify(expected), 'Replica configuration differs');
  requireValue(c.members.every(m => !m.arbiterOnly && !m.hidden && m.votes === 1 && m.priority === 1 && m.buildIndexes !== false), 'Expected three ordinary voting data-bearing members');
  requireValue(command(admin, {buildInfo: 1}).version.startsWith('7.0.'), 'Server major differs from the role contract');
}
function waitHealthy() {
  let failure;
  for (let i=0; i<90; i++) {
    try { return healthy(); } catch (e) { failure = e; sleep(2000); }
  }
  throw failure;
}
function authenticate() {
  const result = admin.auth(env.MONGODB_ADMIN_USER, env.MONGODB_ADMIN_PASSWORD);
  requireValue(result === 1 || result.ok === 1, 'Authentication failed');
}
function bootstrap() {
  requireValue(env.MONGODB_BOOTSTRAP === 'yes', 'Explicit bootstrap permission required');
  // The only unauthenticated path is the server-enforced localhost exception.
  // An auth-disabled server may expose this command without authentication.
  // Never create credentials on such a server or treat it as a fresh bootstrap.
  try { secureOptions(command(admin, {getCmdLineOpts: 1}).parsed); }
  catch (e) { requireValue(e.code === 13, 'Unexpected running security options'); }
  let s;
  try { s = status(); }
  catch (e) {
    requireValue(e.code === 94, 'Existing or unknown state: localhost bootstrap refused');
    requireValue(env.MONGODB_SELF === expected[0].host, 'Only member zero may initiate an uninitialized set');
    command(admin, {replSetInitiate: {_id: env.MONGODB_SET, members: expected}});
    changed = true;
  }
  s = waitHealthy();
  requireValue(s.myState === 1, 'Run bootstrap on the elected primary to create the first user');
  command(admin, {createUser: env.MONGODB_ADMIN_USER, pwd: env.MONGODB_ADMIN_PASSWORD,
    roles: [{role: 'root', db: 'admin'}], writeConcern: {w: 'majority', wtimeout: 30000}});
  changed = true;
  authenticate();
}
function canonicalRoles(roles) {
  return roles.map(r => ({role:r.role, db:r.db})).sort((a,b) => (a.db+'/'+a.role).localeCompare(b.db+'/'+b.role));
}
function manage() {
  const s = healthy();
  requireValue(s.myState === 1, 'Run management on the current primary');
  const users = JSON.parse(env.MONGODB_USERS || '[]');
  const collections = JSON.parse(env.MONGODB_COLLECTIONS || '[]');
  for (const u of users) {
    requireValue(typeof u.database === 'string' && !['local','$external'].includes(u.database) && u.database.length > 0, 'Invalid user authentication database');
    requireValue(typeof u.name === 'string' && u.name.length > 0 && !(u.database === 'admin' && u.name === env.MONGODB_ADMIN_USER), 'Bootstrap administrator is not managed here');
    requireValue(Array.isArray(u.roles) && u.roles.every(r => typeof r.role === 'string' && typeof r.db === 'string'), 'Roles must include explicit role and database');
    requireValue(typeof u.password === 'string' && u.password.length >= 20, 'User password must be supplied from Vault');
    const target = db.getSiblingDB(u.database);
    const current = command(target, {usersInfo: u.name}).users;
    if (current.length === 0) {
      command(target, {createUser: u.name, pwd: u.password, roles: u.roles, writeConcern: {w:'majority', wtimeout:30000}});
      changed = true;
    } else if (JSON.stringify(canonicalRoles(current[0].roles)) !== JSON.stringify(canonicalRoles(u.roles))) {
      command(target, {updateUser:u.name, roles:u.roles, writeConcern:{w:'majority', wtimeout:30000}});
      changed = true;
    }
    // Existing passwords are never implicitly reset on repeated runs.
  }
  for (const c of collections) {
    requireValue(typeof c.database === 'string' && c.database.length > 0 && !['admin','config','local'].includes(c.database), 'Application database required');
    requireValue(typeof c.name === 'string' && c.name.length > 0 && !c.name.startsWith('system.'), 'Application collection required');
    const target = db.getSiblingDB(c.database);
    const present = command(target, {listCollections:1, filter:{name:c.name}, nameOnly:true}).cursor.firstBatch;
    if (!present.length) { command(target, {create:c.name, writeConcern:{w:'majority',wtimeout:30000}}); changed = true; }
  }
}
let authenticated = false;
try { authenticate(); authenticated = true; }
catch (e) {
  requireValue(action === 'bootstrap' && (e.code === 18 || e.message === 'Authentication failed'), 'Authentication failed; no fallback outside explicit localhost bootstrap');
}
if (!authenticated) bootstrap();
verifyConfig();
if (action === 'wait_healthy') waitHealthy();
else if (action === 'prepare_restart') {
  const s = healthy();
  if (s.myState === 1) {
    // No force flag: MongoDB requires an electable, caught-up secondary.
    command(admin, {replSetStepDown:60, secondaryCatchUpPeriodSecs:30});
    const after = waitHealthy();
    requireValue(after.myState === 2, 'Member must step down before restart');
  }
} else if (action === 'manage') manage();
else { requireValue(['bootstrap','status'].includes(action), 'Unknown action'); healthy(); }
print(changed ? 'CHANGED' : 'OK');
