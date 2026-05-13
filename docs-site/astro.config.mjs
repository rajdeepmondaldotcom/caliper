import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  integrations: [
    starlight({
      title: 'Caliper',
      description: 'The cost layer for AI-assisted development. Reads local Codex, Claude Code, Cursor, and Aider logs and prints what each PR cost. Offline.',
      sidebar: [
        {
          label: 'Start',
          items: [
            { label: 'Quickstart', slug: 'quickstart' },
            { label: 'Concepts', slug: 'concepts' },
          ],
        },
      ],
    }),
  ],
});
