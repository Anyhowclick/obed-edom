import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useStoredFile } from "../src/prefs";

const KEY = "test.storedFile.sync";

function Consumer({ label }: { label: string }) {
  const [file, setFile] = useStoredFile(KEY);
  return (
    <div>
      <span data-testid={`${label}-value`}>{file?.name || "none"}</span>
      <button onClick={() => setFile({ path: "/tmp/a.key", name: "a.key" })}>{`${label}-choose`}</button>
      <button onClick={() => setFile(null)}>{`${label}-clear`}</button>
    </div>
  );
}

describe("useStoredFile", () => {
  it("keeps two mounted subscribers on the same key in sync after choose and clear", () => {
    render(
      <>
        <Consumer label="a" />
        <Consumer label="b" />
      </>
    );

    expect(screen.getByTestId("a-value")).toHaveTextContent("none");
    expect(screen.getByTestId("b-value")).toHaveTextContent("none");

    fireEvent.click(screen.getByText("a-choose"));
    expect(screen.getByTestId("a-value")).toHaveTextContent("a.key");
    expect(screen.getByTestId("b-value")).toHaveTextContent("a.key");

    fireEvent.click(screen.getByText("b-clear"));
    expect(screen.getByTestId("a-value")).toHaveTextContent("none");
    expect(screen.getByTestId("b-value")).toHaveTextContent("none");
  });
});
