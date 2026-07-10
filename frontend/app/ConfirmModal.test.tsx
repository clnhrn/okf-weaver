import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ConfirmModal from "./ConfirmModal";

function render(props: Partial<Parameters<typeof ConfirmModal>[0]> = {}) {
  return renderToStaticMarkup(
    <ConfirmModal
      title="Clear schema and bundle?"
      message="This can't be undone."
      onConfirm={() => {}}
      onCancel={() => {}}
      {...props}
    />,
  );
}

describe("ConfirmModal", () => {
  it("renders the title and message", () => {
    const html = render();
    expect(html).toContain("Clear schema and bundle?");
    expect(html).toContain("This can&#x27;t be undone.");
  });

  it("defaults the confirm button label to Confirm", () => {
    const html = render();
    expect(html).toContain(">Confirm<");
  });

  it("uses a custom confirm label when given", () => {
    const html = render({ confirmLabel: "Clear" });
    expect(html).toContain(">Clear<");
    expect(html).not.toContain(">Confirm<");
  });

  it("always renders a Cancel button", () => {
    const html = render();
    expect(html).toContain(">Cancel<");
  });

  it("wires alertdialog semantics so screen readers announce it as a prompt, not a generic panel", () => {
    const html = render();
    expect(html).toContain('role="alertdialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('aria-labelledby="modal-title"');
    expect(html).toContain('aria-describedby="modal-msg"');
    expect(html).toContain('id="modal-title"');
    expect(html).toContain('id="modal-msg"');
  });
});
