import CodeDeltaApp from "@/app/CodeDeltaApp";

export default async function CatchAllPage({
  params,
}: {
  params: Promise<{ route?: string[] }>;
}) {
  const { route = [] } = await params;
  return <CodeDeltaApp route={route} />;
}
