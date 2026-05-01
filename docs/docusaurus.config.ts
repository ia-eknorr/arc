import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'arc',
  tagline: 'Lightweight agent dispatch, scheduling, and Discord integration',
  favicon: 'img/logo.svg',
  url: 'https://ia-eknorr.github.io',
  baseUrl: '/arc/',
  organizationName: 'ia-eknorr',
  projectName: 'arc',
  deploymentBranch: 'gh-pages',
  trailingSlash: false,
  onBrokenLinks: 'throw',
  i18n: {defaultLocale: 'en', locales: ['en']},
  markdown: {mermaid: true, hooks: {onBrokenMarkdownLinks: 'warn'}},
  themes: ['@docusaurus/theme-mermaid'],
  presets: [
    ['classic', {
      docs: {
        sidebarPath: './sidebars.ts',
        routeBasePath: '/',
        editUrl: 'https://github.com/ia-eknorr/arc/edit/main/docs/',
      },
      blog: false,
      theme: {customCss: './src/css/custom.css'},
    } satisfies Preset.Options],
  ],
  themeConfig: {
    image: 'img/logo.svg',
    colorMode: {defaultMode: 'light', disableSwitch: false, respectPrefersColorScheme: true},
    navbar: {
      title: 'arc',
      logo: {alt: 'arc logo', src: 'img/logo.svg'},
      items: [
        {type: 'docSidebar', sidebarId: 'docs', position: 'left', label: 'Docs'},
        {href: 'https://github.com/ia-eknorr/arc', label: 'GitHub', position: 'right'},
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {title: 'Docs', items: [
          {label: 'Introduction', to: '/'},
          {label: 'Quickstart', to: '/getting-started/quickstart'},
          {label: 'CLI Reference', to: '/reference/cli'},
        ]},
        {title: 'Guides', items: [
          {label: 'Agents', to: '/guides/agents'},
          {label: 'Cron Scheduling', to: '/guides/cron-scheduling'},
          {label: 'Discord Integration', to: '/guides/discord'},
        ]},
        {title: 'More', items: [
          {label: 'Changelog', to: '/changelog'},
          {label: 'GitHub', href: 'https://github.com/ia-eknorr/arc'},
        ]},
      ],
      copyright: `Copyright © ${new Date().getFullYear()} arc. MIT License.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'yaml'],
    },
  } satisfies Preset.ThemeConfig,
};
export default config;
