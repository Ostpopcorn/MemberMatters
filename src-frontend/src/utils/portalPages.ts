import type {
  MemberState,
  PageAndRouteConfigType,
} from '../pages/pageAndRouteConfig';

export type PortalPage = {
  name: string;
  params: { [key: string]: string };
  featureEnabled: boolean;
  allowedStates?: MemberState[];
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
      allowedStates: page.allowedStates,
    }));
}

export type CardViewer = {
  memberStatus?: MemberState;
  permissions?: { staff?: boolean };
} | null;

// The links a card shows, with portal pages resolved to router locations.
// Resolving a page that doesn't exist or is missing route parameters would
// throw, the router doesn't check feature flags, and a page the viewer's
// member state can't open would only show a 403, so links to those pages are
// left out, as their menu entries are. Staff bypass the member state check, as
// in the route guard.
export function cardLinks(
  links: CardLink[],
  pages: PortalPage[],
  viewer: CardViewer
) {
  const canOpen = (page: PortalPage) =>
    page.featureEnabled &&
    (!page.allowedStates ||
      viewer?.permissions?.staff === true ||
      (!!viewer?.memberStatus &&
        page.allowedStates.includes(viewer.memberStatus)));

  return links.flatMap((link) => {
    if (!link.route) return [link];
    const page = pages.find((p) => p.name === link.route && canOpen(p));
    return page
      ? [{ ...link, to: { name: page.name, params: page.params } }]
      : [];
  });
}

function routeParams(path: string): string[] {
  return (path.match(/:\w+/g) ?? []).map((param) => param.slice(1));
}
