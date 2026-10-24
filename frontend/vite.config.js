import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// In local dev there is no CloudFront/ALB, so the Vite dev server plays that role:
// it forwards /api/v1/<resource> to the right service port. In AWS, the ALB does this.
// ORDER MATTERS: the first matching rule wins. Sub-resources of a student or teacher belong to the service that
// owns that data (fees, attendance) even though the path starts with /students or /teachers.
// Keys starting with "^" are regular expressions. The same rules live in docker/nginx.conf and, later, the Ingress.
const SERVICE_ROUTES = {
  '^/api/v1/students/[^/]+/fees': 'FEE',
  '^/api/v1/students/[^/]+/attendance': 'ATTENDANCE',
  '^/api/v1/teachers/[^/]+/attendance': 'ATTENDANCE',
  '^/api/v1/(fees|fee-structures|payments)': 'FEE',
  '^/api/v1/attendance': 'ATTENDANCE',
  '^/api/v1/notifications': 'NOTIFICATION',
  '^/api/v1/admissions': 'ADMISSION',
  '^/api/v1/(students|classes|sections|subjects|teachers)': 'STUDENT',
  '^/api/v1/(auth|users)': 'AUTH',
  '/.well-known/jwks.json': 'AUTH',
};

const DEFAULT_PORTS = {
  AUTH: 8001, ADMISSION: 8002, STUDENT: 8003, FEE: 8004, ATTENDANCE: 8005, NOTIFICATION: 8006,
};

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const proxy = Object.fromEntries(
    Object.entries(SERVICE_ROUTES).map(([path, svc]) => [
      path,
      { target: env[`DEV_${svc}_URL`] || `http://localhost:${DEFAULT_PORTS[svc]}`, changeOrigin: true },
    ]),
  );
  return {
    plugins: [react()],
    server: { port: 5173, proxy },
    build: { outDir: 'dist', sourcemap: true },
    test: {
      environment: 'node',
      include: ['src/**/*.test.js'],
      // lcov is the format SonarQube reads; run with `npm run test:coverage`
      coverage: { provider: 'v8', reporter: ['text', 'lcov'], include: ['src/**/*.{js,jsx}'], exclude: ['src/**/*.test.js'] },
    },
  };
});
