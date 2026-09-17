import * as assert from 'assert';
import { detectCline } from '../../cline';

suite('Cline Detection Test Suite', () => {
    test('Should detect Cline status without throwing', () => {
        try {
            const info = detectCline();
            console.log('Cline detection result:', info);
            // It might not be installed in the test environment, which is fine
            if (info.installed) {
                assert.ok(info.version, 'Should have a version if installed');
                assert.ok(info.extensionPath, 'Should expose the public installation path for exact inspection');
            } else {
                assert.strictEqual(info.installed, false);
            }
        } catch (e) {
            assert.fail('Cline detection failed: ' + e);
        }
    });
});
