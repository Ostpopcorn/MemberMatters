import { describe, it, expect } from 'vitest';
import { portalPages } from './portalPages';
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

    expect(portalPages(config).map((p) => p.name)).toEqual([
      'dashboard',
      'reportIssue',
      'proxy',
    ]);
  });

  it('leaves out admin, hidden and logged-out pages', () => {
    const config = [
      page('adminTools', {
        to: undefined,
        admin: true,
        children: [page('signupPreview', { admin: true })],
      }),
      page('kioskOnly', { admin: true }),
      page('resetPassword', { hiddenMenu: true }),
      page('login', { loggedIn: false }),
      page('profile'),
    ];

    expect(portalPages(config).map((p) => p.name)).toEqual(['profile']);
  });

  it('keeps a page with parameters only when they all have defaults, and passes them', () => {
    const config = [
      page('memberbucks', {
        to: '/account/memberbucks/:dialog',
        defaultParams: { dialog: 'transactions' },
      }),
      page('manageTier', { to: '/manage/tiers/:planId' }),
    ];

    expect(portalPages(config)).toEqual([
      { name: 'memberbucks', params: { dialog: 'transactions' } },
    ]);
  });
});
