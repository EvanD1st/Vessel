'use client';

import React, { useEffect, useRef } from 'react';

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  baseColor: string;
  glowColor: string;
  pulseSpeed: number;
  pulsePhase: number;
}

interface PulsePacket {
  fromIndex: number;
  toIndex: number;
  progress: number;
  speed: number;
  color: string;
}

export function CyberCanvas() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    const handleResize = () => {
      if (!canvas) return;
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    };
    window.addEventListener('resize', handleResize);

    const mouse = { x: -1000, y: -1000, active: false };
    const handleMouseMove = (e: MouseEvent) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
      mouse.active = true;
    };
    const handleMouseLeave = () => {
      mouse.active = false;
      mouse.x = -1000;
      mouse.y = -1000;
    };
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseleave', handleMouseLeave);

    const colorPalette = [
      { base: 'rgba(215, 250, 125, 0.75)', glow: 'rgba(215, 250, 125, 0.35)' },
      { base: 'rgba(139, 198, 173, 0.7)', glow: 'rgba(139, 198, 173, 0.3)' },
      { base: 'rgba(64, 124, 105, 0.8)', glow: 'rgba(64, 124, 105, 0.25)' },
      { base: 'rgba(220, 245, 182, 0.6)', glow: 'rgba(220, 245, 182, 0.25)' },
    ];

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const particleCount = Math.min(Math.floor((width * height) / 20000), 60);
    const particles: Particle[] = [];

    for (let i = 0; i < particleCount; i++) {
      const palette = colorPalette[Math.floor(Math.random() * colorPalette.length)];
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * (prefersReducedMotion ? 0 : 0.45),
        vy: (Math.random() - 0.5) * (prefersReducedMotion ? 0 : 0.45),
        radius: Math.random() * 2 + 1.2,
        baseColor: palette.base,
        glowColor: palette.glow,
        pulseSpeed: Math.random() * 0.02 + 0.01,
        pulsePhase: Math.random() * Math.PI * 2,
      });
    }

    const packets: PulsePacket[] = [];
    let lastPacketSpawn = Date.now();
    const maxDistance = 145;

    let isVisible = true;
    const handleVisibilityChange = () => {
      isVisible = !document.hidden;
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    const render = () => {
      if (!ctx || !isVisible) {
        if (!prefersReducedMotion) animationFrameId = requestAnimationFrame(render);
        return;
      }

      ctx.clearRect(0, 0, width, height);

      // Subtle tech grid lines in background
      ctx.strokeStyle = 'rgba(44, 60, 71, 0.15)';
      ctx.lineWidth = 0.5;
      const gridSize = 54;
      ctx.beginPath();
      for (let x = 0; x < width; x += gridSize) {
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
      }
      for (let y = 0; y < height; y += gridSize) {
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
      }
      ctx.stroke();

      const connectedPairs: [number, number][] = [];

      for (let i = 0; i < particles.length; i++) {
        const p1 = particles[i];

        p1.x += p1.vx;
        p1.y += p1.vy;
        if (p1.x < 0 || p1.x > width) p1.vx *= -1;
        if (p1.y < 0 || p1.y > height) p1.vy *= -1;

        p1.pulsePhase += p1.pulseSpeed;

        for (let j = i + 1; j < particles.length; j++) {
          const p2 = particles[j];
          const dx = p1.x - p2.x;
          const dy = p1.y - p2.y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < maxDistance) {
            connectedPairs.push([i, j]);
            const alpha = (1 - dist / maxDistance) * 0.32;
            ctx.strokeStyle = `rgba(139, 198, 173, ${alpha})`;
            ctx.lineWidth = 0.75;
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.stroke();
          }
        }

        if (mouse.active) {
          const mdx = p1.x - mouse.x;
          const mdy = p1.y - mouse.y;
          const mdist = Math.sqrt(mdx * mdx + mdy * mdy);
          if (mdist < 170) {
            const malpha = (1 - mdist / 170) * 0.4;
            ctx.strokeStyle = `rgba(215, 250, 125, ${malpha})`;
            ctx.lineWidth = 0.9;
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(mouse.x, mouse.y);
            ctx.stroke();
          }
        }
      }

      // Random data packets traveling across filaments
      if (!prefersReducedMotion && connectedPairs.length > 0 && Date.now() - lastPacketSpawn > 500) {
        if (Math.random() < 0.8 && packets.length < 10) {
          const pair = connectedPairs[Math.floor(Math.random() * connectedPairs.length)];
          packets.push({
            fromIndex: pair[0],
            toIndex: pair[1],
            progress: 0,
            speed: Math.random() * 0.02 + 0.012,
            color: Math.random() > 0.4 ? '#d7fa7d' : '#8bc6ad',
          });
        }
        lastPacketSpawn = Date.now();
      }

      for (let k = packets.length - 1; k >= 0; k--) {
        const pkt = packets[k];
        pkt.progress += pkt.speed;
        if (pkt.progress >= 1) {
          packets.splice(k, 1);
          continue;
        }

        const pA = particles[pkt.fromIndex];
        const pB = particles[pkt.toIndex];
        if (!pA || !pB) {
          packets.splice(k, 1);
          continue;
        }

        const curX = pA.x + (pB.x - pA.x) * pkt.progress;
        const curY = pA.y + (pB.y - pA.y) * pkt.progress;

        ctx.fillStyle = pkt.color;
        ctx.shadowColor = pkt.color;
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.arc(curX, curY, 2.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        const pulse = Math.sin(p.pulsePhase) * 0.4 + 1;
        const currentRadius = p.radius * pulse;

        ctx.fillStyle = p.glowColor;
        ctx.beginPath();
        ctx.arc(p.x, p.y, currentRadius * 2, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = p.baseColor;
        ctx.beginPath();
        ctx.arc(p.x, p.y, currentRadius, 0, Math.PI * 2);
        ctx.fill();
      }

      if (!prefersReducedMotion) {
        animationFrameId = requestAnimationFrame(render);
      }
    };

    render();

    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseleave', handleMouseLeave);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="cyber-canvas"
      style={{
        position: 'fixed',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 0,
      }}
    />
  );
}
