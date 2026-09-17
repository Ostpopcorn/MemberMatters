import type { PageAndRouteConfigType } from '../pages/pageAndRouteConfig';

export type PortalPage = {
  name: string;
  params: { [key: string]: string };
  featureEnabled: boolean;
};

export type CardLink = {
  label: string;
  url?: string;
  route?: string;
};

// The pages a dashboard card can link to: logged-in menu pages outside Admin
// Tools, except Logout, whose route parameters all have defaults, so they open
// by name alone.
export function portalPages(
  config: PageAndRouteConfigType[],
  features: { [flag: string]: unknown }
): PortalPage[] {
  return config
    .filter((page) => !page.admin)
    .flatMap((page) => [page, ...(page.children ?? [])])
    .filter(
      (page) =>
        page.to &&
        page.loggedIn &&
        !page.admin &&
        !page.hiddenMenu &&
        page.name !== 'logout' &&
        routeParams(page.to).every((param) => page.defaultParams?.[param])
    )
    .map((page) => ({
      name: page.name,
      params: page.defaultParams ?? {},
      featureEnabled:
        !page.featureEnabledFlag || !!features[page.featureEnabledFlag],
    }));
}

// The links a card shows, with portal pages resolved to router locations.
// Resolving a page that doesn't exist or is missing route parameters would
// throw, and the router doesn't check feature flags, so links to those pages
// and to switched-off features are left out, as their menu entries are.
export function cardLinks(links: CardLink[], pages: PortalPage[]) {
  return links.flatMap((link) => {
    if (!link.route) return [link];
    const page = pages.find((p) => p.name === link.route && p.featureEnabled);
    return page
      ? [{ ...link, to: { name: page.name, params: page.params } }]
      : [];
  });
}

function routeParams(path: string): string[] {
  return (path.match(/:\w+/g) ?? []).map((param) => param.slice(1));
}
