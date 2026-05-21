import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { cancelTask, getTasks } from '../../api/endpoints';
import type { TaskInfo } from '../../types';

interface Props {
  pollIntervalMs?: number;
}

function ProgressRow({ task, big = false, onCancel }: { task: TaskInfo; big?: boolean; onCancel?: (id: string) => void }) {
  const percent = task.total > 0 ? Math.round((task.progress / task.total) * 100) : 0;
  const barColor = task.status === 'failed' ? 'bg-red-500'
    : task.status === 'completed' ? 'bg-green-500'
    : 'bg-blue-600';
  return (
    <div className={big ? 'mb-3' : 'mb-2'}>
      <div className="flex justify-between items-baseline mb-1 gap-2">
        <span className={big ? 'text-sm font-semibold' : 'text-xs text-gray-700'}>{task.name}</span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">
            {task.status === 'failed' ? '실패' : `${task.progress}/${task.total} (${percent}%)`}
          </span>
          {onCancel && (task.status === 'running' || task.status === 'pending') && (
            <button
              onClick={() => {
                if (confirm(`"${task.name}" 중단? 진행한 항목은 그대로 유지됨.`)) onCancel(task.task_id);
              }}
              className="flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded bg-red-50 text-red-700 hover:bg-red-100 border border-red-200 font-semibold"
              title="작업 중단"
            >
              <X size={10} strokeWidth={2.5} />
              중단
            </button>
          )}
        </div>
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

  const handleCancel = async (id: string) => {
    try {
      await cancelTask(id);
      // 즉시 UI 갱신 (poll 다음 tick 까지 안 기다림)
      setTasks(prev => prev.map(t => t.task_id === id ? { ...t, status: 'failed', message: '사용자가 중단' } : t));
    } catch (e) {
      alert('중단 실패: 백엔드 응답 없음');
    }
  };

  return (
    <div className="bg-white rounded-lg shadow p-4 mb-4 border-l-4 border-blue-500">
      {master && <ProgressRow task={master} big onCancel={handleCancel} />}
      {subs.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-100">
          {subs.map(t => <ProgressRow key={t.task_id} task={t} onCancel={handleCancel} />)}
        </div>
      )}
    </div>
  );
}
