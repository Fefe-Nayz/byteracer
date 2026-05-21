import { dirname, extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

declare const Bun: {
  env: Record<string, string | undefined>;
  file(path: string): Blob & { exists(): Promise<boolean> };
  serve(options: {
    port: number;
    fetch(request: Request): Response | Promise<Response>;
  }): unknown;
};

const port = Number(Bun.env.PORT ?? "3000");
const root = resolve(dirname(fileURLToPath(import.meta.url)), "out");

const contentTypes: Record<string, string> = {
  ".css": "text/css; charset=utf-8",
  ".gif": "image/gif",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".mp3": "audio/mpeg",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
  ".wasm": "application/wasm",
  ".webp": "image/webp",
};

const cacheControl = (pathname: string) =>
  pathname.startsWith("/_next/static/")
    ? "public, max-age=31536000, immutable"
    : "public, max-age=60";

async function serveFile(pathname: string): Promise<Response | null> {
  const target = resolve(root, pathname === "/" ? "index.html" : `.${pathname}`);

  if (target !== root && !target.startsWith(`${root}${sep}`)) {
    return new Response("Forbidden", { status: 403 });
  }

  const file = Bun.file(target);
  if (!(await file.exists())) return null;

  const contentType = contentTypes[extname(target)] ?? "application/octet-stream";
  return new Response(file, {
    headers: {
      "Cache-Control": cacheControl(pathname),
      "Content-Type": contentType,
    },
  });
}

Bun.serve({
  port,
  async fetch(request) {
    const url = new URL(request.url);
    let pathname = "/";
    try {
      pathname = decodeURIComponent(url.pathname);
    } catch {
      return new Response("Bad request", { status: 400 });
    }

    const direct = await serveFile(pathname);
    if (direct) return direct;

    if (!pathname.includes(".")) {
      const page = await serveFile(`${pathname}/index.html`);
      if (page) return page;

      const fallback = await serveFile("/");
      if (fallback) return fallback;
    }

    return new Response("Not found", { status: 404 });
  },
});

console.log(`RelayTower static server listening on http://0.0.0.0:${port}`);
