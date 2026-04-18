import { useEffect, useState } from 'react';
import type { TaskInfo } from '../types';

export function useSSE(taskId: string | null) {
  const [task, setTask] = useState<TaskInfo | null>(null);

  useEffect(() => {
    if (!taskId) return;

    const eventSource = new EventSource(`/api/tasks/${taskId}/stream`);

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data) as TaskInfo;
      setTask(data);
      if (data.status === 'completed' || data.status === 'failed') {
        eventSource.close();
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [taskId]);

  return task;
}
