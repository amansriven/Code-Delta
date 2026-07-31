import DeltaCodeApp from "@/app/DeltaCodeApp";

export default async function CatchAllPage({
  params,
}: {
  params: Promise<{ route?: string[] }>;
}) {
  const { route = [] } = await params;
  return <DeltaCodeApp route={route} />;
}
