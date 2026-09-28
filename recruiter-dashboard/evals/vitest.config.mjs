import { defineConfig } from 'vitest/config'

// Evals hit live APIs and cost money, so they run only via
// `npm run eval:sorting`, never as part of `npm test`.
export default defineConfig({
  test: {
    include: ['evals/**/*.eval.js'],
    testTimeout: 30 * 60 * 1000,
  },
})
