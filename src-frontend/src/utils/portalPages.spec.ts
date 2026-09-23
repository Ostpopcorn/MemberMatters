import { describe, it, expect } from 'vitest';
import { cardLinks, portalPages } from './portalPages';
import type { PortalPage } from './portalPages';
import type { PageAndRouteConfigType } from '../pages/pageAndRouteConfig';

const page = (
  name: string,
  extra: Partial<PageAndRouteConfigType> = {}
): PageAndRouteConfigType => ({
  icon: 'mdi-test',
  name,
  to: `/${name}`,
  loggedIn: true,
  ...extra,
});

describe('portalPages', () => {
  it('lists logged-in pages and the children of member menus', () => {
    const config = [
      page('dashboard'),
      page('memberTools', {
        to: undefined,
        children: [page('reportIssue'), page('proxy')],
      }),
    ];

    expect(portalPages(config, {}).map((p) => p.name)).toEqual([
      'dashboard',
      'reportIssue',
      'proxy',
    ]);
  });

  it('leaves out admin, hidden, logged-out and logout pages', () => {
    const config = [
      page('adminTools', {
        to: undefined,
        admin: true,
        children: [page('signupPreview', { admin: true })],
      }),
      page('kioskOnly', { admin: true }),
      page('resetPassword', { hiddenMenu: true }),
      page('login', { loggedIn: false }),
      page('logout'),
      page('profile'),
    ];

    expect(portalPages(config, {}).map((p) => p.name)).toEqual(['profile']);
  });

  it('keeps a page with parameters only when they all have defaults, and passes them', () => {
    const config = [
      page('memberbucks', {
        to: '/account/memberbucks/:dialog',
        defaultParams: { dialog: 'transactions' },
      }),
      page('manageTier', { to: '/manage/tiers/:planId' }),
    ];

    expect(portalPages(config, {})).toEqual([
      {
        name: 'memberbucks',
        params: { dialog: 'transactions' },
        featureEnabled: true,
      },
    ]);
  });

  it('marks pages whose feature is switched off', () => {
    const config = [
      page('webcams', { featureEnabledFlag: 'enableWebcams' }),
      page('stats', { featureEnabledFlag: 'enableStatsPage' }),
      page('profile'),
    ];
    const features = { enableWebcams: true, enableStatsPage: false };

    expect(
      portalPages(config, features).map((p) => [p.name, p.featureEnabled])
    ).toEqual([
      ['webcams', true],
      ['stats', false],
      ['profile', true],
    ]);
  });
});

describe('cardLinks', () => {
  const pages: PortalPage[] = [
    {
      name: 'memberbucks',
      params: { dialog: 'transactions' },
      featureEnabled: true,
    },
    { name: 'webcams', params: {}, featureEnabled: false },
    {
      name: 'reportIssue',
      params: {},
      featureEnabled: true,
      allowedStates: ['active'],
    },
  ];
  const member = { memberStatus: 'active' as const };

  it('keeps website links and resolves portal pages with their parameters', () => {
    const links = [
      { label: 'Wiki', url: 'https://bms.wiki' },
      { label: 'Top up', route: 'memberbucks' },
    ];

    expect(cardLinks(links, pages, member)).toEqual([
      { label: 'Wiki', url: 'https://bms.wiki' },
      {
        label: 'Top up',
        route: 'memberbucks',
        to: { name: 'memberbucks', params: { dialog: 'transactions' } },
      },
    ]);
  });

  it('leaves out unknown pages and switched-off features', () => {
    const links = [
      { label: 'Gone', route: 'removedPage' },
      { label: 'Cameras', route: 'webcams' },
    ];

    expect(cardLinks(links, pages, member)).toEqual([]);
  });

  it("leaves out pages the viewer's member state can't open, except for staff", () => {
    const links = [{ label: 'Report', route: 'reportIssue' }];
    const labels = (viewer: Parameters<typeof cardLinks>[2]) =>
      cardLinks(links, pages, viewer).map((link) => link.label);

    expect(labels({ memberStatus: 'active' })).toEqual(['Report']);
    expect(labels({ memberStatus: 'inactive' })).toEqual([]);
    expect(labels({})).toEqual([]);
    expect(labels(null)).toEqual([]);
    expect(
      labels({ memberStatus: 'noob', permissions: { staff: true } })
    ).toEqual(['Report']);
  });
});
