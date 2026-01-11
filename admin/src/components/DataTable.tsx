interface Column<T> {
  key: keyof T | string;
  title: string;
  render?: (item: T) => React.ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  onDelete?: (item: T) => void;
}

export function DataTable<T extends { id: number }>({
  columns,
  data,
  onDelete,
}: DataTableProps<T>) {
  return (
    <div className="overflow-hidden rounded-xl bg-gray-900">
      <table className="min-w-full divide-y divide-gray-800">
        <thead className="bg-gray-800/50">
          <tr>
            {columns.map((col) => (
              <th
                key={String(col.key)}
                className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-400"
              >
                {col.title}
              </th>
            ))}
            {onDelete && (
              <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-400">
                Actions
              </th>
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {data.map((item) => (
            <tr key={item.id} className="hover:bg-gray-800/50">
              {columns.map((col) => (
                <td
                  key={String(col.key)}
                  className="whitespace-nowrap px-6 py-4 text-sm text-gray-300"
                >
                  {col.render
                    ? col.render(item)
                    : String((item as Record<string, unknown>)[col.key as string] ?? '-')}
                </td>
              ))}
              {onDelete && (
                <td className="whitespace-nowrap px-6 py-4 text-right text-sm">
                  <button
                    onClick={() => onDelete(item)}
                    className="text-red-400 hover:text-red-300"
                  >
                    Delete
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {data.length === 0 && (
        <div className="py-12 text-center text-gray-500">No data</div>
      )}
    </div>
  );
}
