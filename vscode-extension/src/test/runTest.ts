import * as path from 'path';

import { runTests } from '@vscode/test-electron';

async function main() {
	try {
		// The folder containing the Extension Manifest package.json
		// Passed to `--extensionDevelopmentPath`
		const extensionDevelopmentPath = path.resolve(__dirname, '../../');

		// The path to the extension test script
		// Passed to --extensionTestsPath
		const extensionTestsPath = path.resolve(__dirname, './suite/index');

		// Download VS Code, unzip it and run the integration test
		await runTests({ extensionDevelopmentPath, extensionTestsPath,
            vscodeExecutablePath: process.env.VESSEL_TEST_VSCODE,
            launchArgs: ['--disable-extensions', '--disable-telemetry',
                `--user-data-dir=${path.join(extensionDevelopmentPath, '.vscode-test', 'test-profile')}`,
                `--extensions-dir=${path.join(extensionDevelopmentPath, '.vscode-test', 'test-extensions')}`],
            extensionTestsEnv: { VESSEL_REGISTRY_DIR: path.join(extensionDevelopmentPath, '.vscode-test', 'registry') }
        });
	} catch (err) {
		console.error('Failed to run tests', err);
		process.exit(1);
	}
}

main();
