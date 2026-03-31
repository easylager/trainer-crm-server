// k6 load profile for public catalog + health.
// Usage: BASE_URL=http://127.0.0.1:8000 k6 run scripts/loadtest/k6/public_catalog.js
// Disable API rate limit on the target when testing from one IP: API_RATE_LIMIT_ENABLED=false

import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.BASE_URL || 'http://127.0.0.1:8000';

export const options = {
  stages: [
    { duration: '20s', target: 15 },
    { duration: '40s', target: 40 },
    { duration: '20s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<5000'],
  },
};

const paths = [
  '/health',
  '/api/public/cities',
  '/api/public/services',
  '/api/public/trainers?limit=12',
];

export default function () {
  const path = paths[Math.floor(Math.random() * paths.length)];
  const res = http.get(`${BASE}${path}`);
  check(res, {
    'status 2xx or 429': (r) => (r.status >= 200 && r.status < 300) || r.status === 429,
  });
  sleep(0.3);
}
