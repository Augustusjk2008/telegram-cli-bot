import { afterEach, expect, test, vi } from "vitest";
import { WebApiClientError } from "../services/types";
import { deletePathWithReadonlyConfirmation } from "../utils/deletePath";

const readonlyError = new WebApiClientError("文件为只读文件。确定取消只读并删除吗？", {
  status: 409,
  code: "readonly_confirmation_required",
});

afterEach(() => vi.restoreAllMocks());

test("deletes an ordinary file without a read-only confirmation", async () => {
  const confirm = vi.spyOn(window, "confirm");
  const remove = vi.fn().mockResolvedValue(undefined);

  expect(await deletePathWithReadonlyConfirmation(remove)).toBe(true);
  expect(remove).toHaveBeenCalledTimes(1);
  expect(confirm).not.toHaveBeenCalled();
});

test.each([true, false])("read-only deletion honors confirmation=%s", async (approved) => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(approved);
  const remove = vi.fn().mockRejectedValueOnce(readonlyError).mockResolvedValue(undefined);

  expect(await deletePathWithReadonlyConfirmation(remove)).toBe(approved);
  expect(confirm).toHaveBeenCalledExactlyOnceWith(readonlyError.message);
  expect(remove).toHaveBeenCalledTimes(approved ? 2 : 1);
  if (approved) {
    expect(remove).toHaveBeenLastCalledWith({ confirmReadonly: true });
  }
});

test("other deletion errors are reported without requesting read-only confirmation", async () => {
  const confirm = vi.spyOn(window, "confirm");
  const error = new WebApiClientError("拒绝访问", { status: 500, code: "delete_path_failed" });
  const remove = vi.fn().mockRejectedValue(error);

  await expect(deletePathWithReadonlyConfirmation(remove)).rejects.toBe(error);
  expect(confirm).not.toHaveBeenCalled();
});

test("a failed confirmed deletion is reported after one read-only prompt", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  const remove = vi.fn().mockRejectedValue(readonlyError);

  await expect(deletePathWithReadonlyConfirmation(remove)).rejects.toBe(readonlyError);
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(remove).toHaveBeenCalledTimes(2);
});
