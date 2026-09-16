import type { PageAndRouteConfigType } from '../pages/pageAndRouteConfig';

export type PortalPage = {
  name: string;
  params: { [key: string]: string };
};

// The pages a dashboard card can link to: logged-in menu pages outside Admin
// Tools whose route parameters all have defaults, so they open by name alone.
export function portalPages(config: PageAndRouteConfigType[]): PortalPage[] {
  return config
    .filter((page) => !page.admin)
    .flatMap((page) => [page, ...(page.children ?? [])])
    .filter(
      (page) =>
        page.to &&
        page.loggedIn &&
        !page.admin &&
        !page.hiddenMenu &&
        routeParams(page.to).every((param) => page.defaultParams?.[param])
    )
    .map((page) => ({ name: page.name, params: page.defaultParams ?? {} }));
}

function routeParams(path: string): string[] {
  return (path.match(/:\w+/g) ?? []).map((param) => param.slice(1));
}
