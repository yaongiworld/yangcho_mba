/**
 * Brief Detail — page 3.
 *
 * Full chain per moment: trend → friction → matched product → marketing playbook.
 * Always shows the "Product data sourced from public product pages, last refreshed [date]"
 * disclaimer. Click-through to source URL respects dead-link suppression.
 *
 * Implementation lands in W5.
 */

export default async function BriefDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <h1 className="text-3xl font-semibold">Brief #{id}</h1>
      <p className="mt-3 text-neutral-500">
        Full friction → product → playbook chain. Placeholder — W5.
      </p>
    </main>
  );
}
