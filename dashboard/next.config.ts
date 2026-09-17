import type { NextConfig } from 'next';

const nextConfig: NextConfig = process.env.VESSEL_TARGET === 'node' ? { output: 'standalone' } : {};

export default nextConfig;
