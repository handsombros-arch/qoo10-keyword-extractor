import type { TaskInfo } from '../../types';

interface Props {
  task: TaskInfo | null;
}

export default function ProgressBar({ task }: Props) {
  if (!task || task.status === 'completed') return null;

  const percent = task.total > 0 ? Math.round((task.progress / task.total) * 100) : 0;

  return (
    <div className="bg-white rounded-lg shadow p-4 mb-4">
      <div className="flex justify-between text-sm mb-2">
        <span className="font-medium">{task.name}</span>
        <span className="text-gray-500">
          {task.status === 'failed' ? '실패' : `${task.progress}/${task.total} (${percent}%)`}
        </span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2.5">
        <div
          className={`h-2.5 rounded-full transition-all ${
            task.status === 'failed' ? 'bg-red-500' : 'bg-blue-600'
          }`}
          style={{ width: `${percent}%` }}
        />
      </div>
      {task.message && (
        <p className="text-xs text-gray-500 mt-1">{task.message}</p>
      )}
    </div>
  );
}
