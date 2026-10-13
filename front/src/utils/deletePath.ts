import { WebApiClientError, type FileDeleteOptions } from "../services/types";

export async function deletePathWithReadonlyConfirmation(
  deletePath: (options?: FileDeleteOptions) => Promise<void>,
): Promise<boolean> {
  try {
    await deletePath();
  } catch (error) {
    if (!(error instanceof WebApiClientError) || error.code !== "readonly_confirmation_required") {
      throw error;
    }
    if (!window.confirm(error.message)) {
      return false;
    }
    await deletePath({ confirmReadonly: true });
  }
  return true;
}
