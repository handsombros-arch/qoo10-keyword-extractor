import { useEffect, useState } from 'react';
import { getTasks } from '../../api/endpoints';
import type { TaskInfo } from '../../types';

interface Props {
  pollIntervalMs?: number;
}

function ProgressRow({ task, big = false }: { task: TaskInfo; big?: boolean }) {
  const percent = task.total > 0 ? Math.round((task.progress / task.total) * 100) : 0;
  const barColor = task.status === 'failed' ? 'bg-red-500'
    : task.status === 'completed' ? 'bg-green-500'
    : 'bg-blue-600';
  return (
    <div className={big ? 'mb-3' : 'mb-2'}>
      <div className="flex justify-between items-baseline mb-1">
        <span className={big ? 'text-sm font-semibold' : 'text-xs text-gray-700'}>{task.name}</span>
        <span className="text-xs text-gray-500">
          {task.status === 'failed' ? '실패' : `${task.progress}/${task.total} (${percent}%)`}
        </span>
      </div>
      <div className={`w-full bg-gray-200 rounded-full ${big ? 'h-3' : 'h-1.5'}`}>
        <div className={`${big ? 'h-3' : 'h-1.5'} rounded-full transition-all ${barColor}`} style={{ width: `${percent}%` }} />
      </div>
      {task.message && (
        <p className="text-[11px] text-gray-500 mt-0.5 truncate" title={task.message}>{task.message}</p>
      )}
    </div>
  );
}

export default function TaskProgressPanel({ pollIntervalMs = 1000 }: Props) {
  const [tasks, setTasks] = useState<TaskInfo[]>([]);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await getTasks();
        if (!cancelled) setTasks(res.data);
      } catch { /* ignore */ }
    };
    tick();
    const id = setInterval(tick, pollIntervalMs);
    return () => { cancelled = true; clearInterval(id); };
  }, [pollIntervalMs]);

  // 최근 5초 이내 완료된 task도 잠깐 보여주고 싶지만, status 기반으로만 처리
  const visible = tasks.filter(t => t.status === 'running' || t.status === 'pending');
  if (visible.length === 0) return null;

  // master(이름에 "키워드 수집" 포함)와 sub 분리
  const master = visible.find(t => t.name.includes('키워드 수집'));
  const subs = visible.filter(t => t !== master);

  return (
    <div className="bg-white rounded-lg shadow p-4 mb-4 border-l-4 border-blue-500">
      {master && <ProgressRow task={master} big />}
      {subs.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-100">
          {subs.map(t => <ProgressRow key={t.task_id} task={t} />)}
        </div>
      )}
    </div>
  );
}
