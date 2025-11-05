import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  distDir: "build",
  output: "export",
  // ESLint configuration for builds
  eslint: {
    // Keep ESLint enabled during builds (warnings won't fail the build)
    ignoreDuringBuilds: false,
  },
  typescript: {
    // Allow build to continue with TypeScript errors (they become warnings)
    ignoreBuildErrors: true,
  },
}

export default nextConfig
