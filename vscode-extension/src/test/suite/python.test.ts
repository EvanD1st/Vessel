import * as assert from 'assert';
import { detectPython } from '../../python';

suite('Python Detection Test Suite', () => {
    test('Should detect Python 3.11+', async () => {
        try {
            const info = await detectPython();
            assert.ok(info.executable, 'Should have an executable path');
            assert.ok(info.version, 'Should have a version string');
            console.log(`Detected Python: ${info.version} at ${info.executable}`);
        } catch (e) {
            assert.fail('Python detection failed: ' + e);
        }
    });
});
