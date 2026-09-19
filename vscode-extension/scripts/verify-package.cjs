const { execFileSync } = require('node:child_process');
const path = require('node:path');
const pkg = require('../package.json');
const vsixName = `vessel-companion-${pkg.version}.vsix`;
const python = process.env.VESSEL_TEST_PYTHON || (process.platform === 'win32' ? 'py' : 'python3');
const prefix = python === 'py' ? ['-3.11'] : [];
const script = `import hashlib,json,sys,zipfile
vsix_file = sys.argv[1]
with zipfile.ZipFile(vsix_file) as z:
 names=z.namelist()
 for required in ['extension/package.json','extension/readme.md','extension/resources/icon.svg','extension/scripts/bootstrap.py','extension/runtime/manifest.json','extension/dist/extension.js']:
  assert required in [name.lower() for name in names], required
 assert not any('/node_modules/' in n or '/out/' in n or '/src/' in n or n.endswith(('.sqlite3','.log','.env')) or 'key.dat' in n for n in names)
 manifest=json.loads(z.read('extension/runtime/manifest.json'))
 for name,expected in manifest['files'].items():
  assert hashlib.sha256(z.read('extension/runtime/'+name)).hexdigest()==expected,name
 import io
 wheel=next(n for n in names if 'vessel_continuity-' in n and n.endswith('.whl'))
 with zipfile.ZipFile(io.BytesIO(z.read(wheel))) as w:
  assert 'vessel/extension_api.py' in w.namelist()
  assert 'vessel/extension_gateway.py' in w.namelist()
 print(json.dumps({'entries':len(names),'runtime_wheels':sum(n.endswith('.whl') for n in names),'hashes_verified':True}))
`;
process.stdout.write(execFileSync(python, [...prefix, '-I', '-c', script, vsixName], { cwd: path.resolve(__dirname, '..'), encoding: 'utf8' }));
