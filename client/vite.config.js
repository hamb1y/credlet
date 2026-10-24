import {defineConfig} from 'vite';
import {svelte} from '@sveltejs/vite-plugin-svelte';
export default defineConfig({root:'client',base:'./',plugins:[svelte({compilerOptions:{fragments:'tree'}})],build:{target:'es2022',outDir:'dist',emptyOutDir:true},server:{host:'127.0.0.1',port:1420,strictPort:true}});
