import * as assert from 'assert';
import { PythonCli } from '../../pythonCli';

suite('Python CLI Test Suite', () => {
    test('Should instantiate Python CLI', () => {
        const cli = new PythonCli('python', '/fake/path');
        assert.ok(cli, 'CLI should be instantiated');
    });
});
