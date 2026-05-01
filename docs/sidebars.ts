import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docs: [
    {type: 'category', label: 'Overview', collapsed: false, items: [
      'overview/introduction',
      'overview/architecture',
      'overview/concepts',
    ]},
    {type: 'category', label: 'Getting Started', collapsed: false, items: [
      'getting-started/quickstart',
      'getting-started/installation',
    ]},
    {type: 'category', label: 'Guides', collapsed: false, items: [
      'guides/agents',
      'guides/cron-scheduling',
      'guides/discord',
      'guides/model-routing',
      'guides/migration',
    ]},
    {type: 'category', label: 'Reference', collapsed: false, items: [
      'reference/cli',
      'reference/agent-schema',
      'reference/config-schema',
      'reference/cron-schema',
      'reference/troubleshooting',
    ]},
  ],
};
export default sidebars;
