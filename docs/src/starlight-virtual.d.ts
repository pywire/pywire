// Starlight 0.42 no longer ships type declarations for its virtual modules,
// but the runtime modules still exist. Declare the one this project imports.
declare module 'virtual:starlight/user-config' {
  const config: import('@astrojs/starlight/types').StarlightConfig
  export default config
}
