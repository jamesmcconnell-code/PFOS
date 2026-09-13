import type { NextConfig } from 'next';
const nextConfig: NextConfig = process.env.PFOS_DESKTOP_BUILD === '1'
  ? {output: 'export', trailingSlash: true, images: {unoptimized: true}}
  : {};
export default nextConfig;
