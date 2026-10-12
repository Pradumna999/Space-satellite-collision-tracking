import { DEFAULT_THEME, PAIRS, themeVars } from "./theme";

describe("design tokens", () => {
  it("defaults to pairing D (Ignition), dark, as in the design file", () => {
    expect(DEFAULT_THEME.pairing).toBe("D");
    expect(DEFAULT_THEME.mode).toBe("dark");
    const v = themeVars(DEFAULT_THEME);
    expect(v["--bg"]).toBe(PAIRS.D.dark.bg);
    expect(v["--acc"]).toBe("oklch(0.600 0.22 28)");
    expect(v["--r"]).toBe("0px");
    expect(v["--fh"]).toContain("Fjalla One");
  });
  it("applies the accent hue shift modulo 360", () => {
    const v = themeVars({ ...DEFAULT_THEME, accentHue: -40 });
    expect(v["--acc"]).toBe("oklch(0.600 0.22 348)");
  });
  it("Kyoto uses rounded corners and Quicksand", () => {
    const v = themeVars({ ...DEFAULT_THEME, pairing: "E" });
    expect(v["--r"]).toBe("8px");
    expect(v["--fb"]).toContain("Quicksand");
  });
});
