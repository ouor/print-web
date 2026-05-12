import { defineConfig } from 'orval'

export default defineConfig({
  printWeb: {
    input: {
      // Run backend first (`uvicorn`) before `npm run gen`.
      target: 'http://127.0.0.1:8000/openapi.json',
    },
    output: {
      mode: 'split',
      target: 'src/api/generated/printWeb.ts',
      schemas: 'src/api/generated/model',
      client: 'react-query',
      httpClient: 'axios',
      override: {
        mutator: {
          path: 'src/api/client.ts',
          name: 'apiMutator',
        },
        query: {
          useQuery: true,
          useMutation: true,
          signal: true,
        },
      },
      clean: true,
      prettier: false,
    },
  },
})
