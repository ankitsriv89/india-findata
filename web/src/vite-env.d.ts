/// <reference types="vite/client" />

// Vite injects environment variables under import.meta.env at build time.
// This declaration teaches TypeScript about the project-specific vars we read,
// so `import.meta.env.VITE_API_URL` type-checks instead of erroring with
// "Property 'env' does not exist on type 'ImportMeta'".
interface ImportMetaEnv {
  readonly VITE_API_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
