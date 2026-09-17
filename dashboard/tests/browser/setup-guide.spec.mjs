import { test, expect } from '@playwright/test';

test('all eight steps are readable and installation is truthfully disabled', async ({ page }) => {
  await page.goto('/setup-guide');
  const steps = page.getByRole('list', { name: 'VESSEL setup steps' }).getByRole('listitem');
  await expect(steps).toHaveCount(8);
  for (const step of await steps.all()) await expect(step).toBeVisible();
  await expect(page.getByText('This is an educational preview.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Open in VS Code — preview only' })).toBeDisabled();
  await expect(page.locator('a[href^="vscode:"]')).toHaveCount(0);
});

test('keyboard play, pause, replay, and finite completion', async ({ page }) => {
  await page.goto('/setup-guide');
  const play = page.getByRole('button', { name: 'Play animation', exact: true });
  await expect(play).toBeEnabled();
  await page.clock.install();
  await page.keyboard.press('Tab');
  await expect(play).toBeFocused();
  await page.keyboard.press('Space');
  await expect(page.getByRole('button', { name: 'Pause animation' })).toBeVisible();
  await page.clock.runFor(1900);
  await expect(page.getByRole('status')).toHaveText('Step 2 of 8');
  await page.getByRole('button', { name: 'Pause animation' }).click();
  await page.clock.runFor(6000);
  await expect(page.getByRole('status')).toHaveText('Step 2 of 8');
  await page.getByRole('button', { name: 'Replay animation' }).click();
  await expect(page.getByRole('status')).toHaveText('Step 1 of 8');
  for (let step = 2; step <= 8; step++) {
    await page.clock.runFor(1810);
    await expect(page.getByRole('status')).toHaveText(`Step ${step} of 8`);
  }
  await expect(page.getByRole('button', { name: 'Play animation', exact: true })).toBeVisible();
  await page.clock.runFor(10000);
  await expect(page.getByRole('status')).toHaveText('Step 8 of 8');
});

test('reduced motion stays static', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/setup-guide');
  await expect(page.getByRole('status')).toHaveText('Reduced motion: static guide');
  await expect(page.getByRole('button', { name: 'Play animation', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Replay animation' }).click();
  expect(await page.locator('.setup-guide-steps li').first().evaluate(element => getComputedStyle(element).transitionDuration)).toBe('0s');
  await expect(page.getByRole('heading', { name: 'Recover when needed' })).toBeVisible();
});

test('JavaScript-disabled fallback shows every step', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto('http://localhost:3011/setup-guide');
  const steps = page.locator('.setup-guide-steps li');
  await expect(steps).toHaveCount(8);
  for (const step of await steps.all()) await expect(step).toBeVisible();
  await expect(page.getByText('The complete guide is shown above.', { exact: false })).toBeVisible();
  await context.close();
});

for (const width of [320, 375, 1280]) {
  test(`guide fits ${width}px viewport`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/setup-guide');
    await expect(page.getByRole('heading', { name: 'Keep your work within reach.' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  });
}
