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

test('guide links back to sign in', async ({ page }) => {
  await page.goto('/setup-guide');
  const backLink = page.getByRole('link', { name: 'Back to sign in' });
  await expect(backLink).toBeVisible();
  await expect(backLink).toHaveAttribute('href', '/');
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
