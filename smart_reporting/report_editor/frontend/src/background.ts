export function runInBackground(
  task: Promise<unknown>,
  onError: (error: unknown) => void = () => {},
): void {
  void task.catch(onError)
}
