'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Layers, Play, Pause, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';

const STEPS = [
  ['Install VESSEL', 'Install the local preview VSIX in VS Code. Installation alone does not configure your project.'],
  ['Check requirements', 'VESSEL checks Python 3.11 or newer and the exact supported Cline build before making changes.'],
  ['Choose a project', 'Choose one open folder. Review its mission and the private recovery storage outside your repository.'],
  ['Connect Orbio', 'Approve small verification requests and save your key in VS Code SecretStorage. Project content is not part of this check.'],
  ['Choose two models', 'Choose verified primary and fallback routes. Native Cline compatibility remains a separate check.'],
  ['Configure locally', 'Review hooks, MCP settings, local ports and any compatibility change before applying them.'],
  ['Verify protection', 'Check the companion and gateway, bind an observed Cline task, then verify real capture and a checkpoint. Pending checks stay pending.'],
  ['Recover when needed', 'Stop the source, review a handover for a fresh task, retrieve its context, and confirm observed continuation.'],
];

export default function SetupGuide() {
  const [activeStep, setActiveStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => { setReducedMotion(preference.matches); if (preference.matches) setPlaying(false); setReady(true); };
    const initial = window.setTimeout(update, 0);
    preference.addEventListener('change', update);
    return () => { window.clearTimeout(initial); preference.removeEventListener('change', update); };
  }, []);

  useEffect(() => {
    if (!playing || reducedMotion) return;
    const timer = window.setTimeout(() => {
      const next = Math.min(activeStep + 1, STEPS.length - 1);
      setActiveStep(next);
      if (next === STEPS.length - 1) setPlaying(false);
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [activeStep, playing, reducedMotion]);

  return (
    <main className="login-page setup-guide-page">
      <section className="login-card setup-guide-card" aria-labelledby="setup-title">
        <div className="login-brand"><Layers aria-hidden="true" size={28} /><span>VESSEL</span></div>
        <p className="setup-guide-kicker">LOCAL PREVIEW · SETUP GUIDE</p>
        <h1 id="setup-title">Keep your work within reach.</h1>
        <p>This is an educational preview. Installation and setup happen in VS Code; viewing this page changes nothing on your computer.</p>
        <p>Install the local VESSEL VSIX, then choose <strong>Set up VESSEL</strong>. The current preview supports Windows x64, Python 3.11–3.14, and the verified Cline 4.1.17 bundle.</p>
        <div className="setup-guide-controls">
          <Button variant="outline" disabled={!ready || reducedMotion} aria-label={playing ? 'Pause animation' : 'Play animation'} onClick={() => {
            if (!playing && activeStep === STEPS.length - 1) setActiveStep(0);
            setPlaying(!playing);
          }}>{playing ? <Pause aria-hidden="true" size={16} /> : <Play aria-hidden="true" size={16} />}{playing ? 'Pause' : 'Play'}</Button>
          <Button variant="outline" disabled={!ready} aria-label="Replay animation" onClick={() => { setActiveStep(0); setPlaying(!reducedMotion); }}><RotateCcw aria-hidden="true" size={16} />Replay</Button>
          <output aria-live="polite">{reducedMotion ? 'Reduced motion: static guide' : `Step ${activeStep + 1} of ${STEPS.length}`}</output>
        </div>
        <ol className="setup-guide-steps" aria-label="VESSEL setup steps">
          {STEPS.map(([title, description], index) => (
            <li key={title} aria-current={index === activeStep ? 'step' : undefined}>
              <span className="setup-guide-number" aria-hidden="true">{index + 1}</span>
              <div><h2>{title}</h2><p>{description}</p></div>
            </li>
          ))}
        </ol>
        <p>The complete guide is shown above. Animation is optional and requires JavaScript.</p>
        <div className="setup-guide-footer">
          <Button disabled aria-describedby="marketplace-note">Open in VS Code — preview only</Button>
          <p id="marketplace-note">A Marketplace listing is not available. Use the locally packaged VSIX.</p>
          <Link href="/">Back to sign in</Link>
        </div>
      </section>
    </main>
  );
}
