import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "./App";

describe("App Step 01 placeholder", () => {
  it("renders Arabic RTL layout with Preliminary classification label", () => {
    const html = renderToStaticMarkup(<App initialLang="ar" />);
    expect(html).toContain('dir="rtl"');
    expect(html).toContain('lang="ar"');
    expect(html).toContain("الوكيل الهندسي الاستشاري المحلي");
    expect(html).toContain("Preliminary");
  });

  it("renders English LTR layout when toggled", () => {
    const html = renderToStaticMarkup(<App initialLang="en" />);
    expect(html).toContain('dir="ltr"');
    expect(html).toContain('lang="en"');
    expect(html).toContain("Local AI Engineering Consultancy Agent");
  });
});
