import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CustomFilterProps } from 'ag-grid-react';
import { useGridFilter } from 'ag-grid-react';

/**
 * 엑셀 스타일 체크박스 필터 (AG Grid v32+ React Custom Filter API).
 * - 컬럼 고유값을 체크박스로 표시
 * - "확인" 클릭 시 필터 적용
 */
const CheckboxSetFilter = (props: CustomFilterProps) => {
  const { model, onModelChange, getValue, api, colDef } = props;

  const field = (colDef as any).field as string;

  // 그리드의 모든 행에서 컬럼 고유값 수집
  const allValues = useMemo(() => {
    const set = new Set<string>();
    api.forEachNode((node: any) => {
      let v: any;
      try {
        v = getValue ? getValue(node) : node.data?.[field];
      } catch {
        v = node.data?.[field];
      }
      const key = v == null || v === '' ? '(빈 값)' : String(v);
      set.add(key);
    });
    return Array.from(set).sort((a, b) => {
      const na = Number(a); const nb = Number(b);
      if (!isNaN(na) && !isNaN(nb)) return na - nb;
      return a.localeCompare(b);
    });
  }, [api, field, getValue]);

  // 현재 적용된 모델로부터 selectedSet 계산
  const selectedFromModel = useMemo<Set<string>>(() => {
    if (model && Array.isArray(model.values)) return new Set(model.values);
    return new Set(allValues);
  }, [model, allValues]);

  const [draft, setDraft] = useState<Set<string>>(selectedFromModel);
  const [search, setSearch] = useState('');

  // model이 외부에서 바뀌면 draft 동기화
  useEffect(() => {
    setDraft(new Set(selectedFromModel));
  }, [selectedFromModel]);

  // model을 ref에 동기화 (closure 문제 회피)
  const modelRef = useRef(model);
  useEffect(() => { modelRef.current = model; }, [model]);

  // 필터 통과 여부 (안정된 콜백, ref로 최신 model 참조)
  const doesFilterPass = useCallback((params: any) => {
    const m = modelRef.current;
    if (!m || !Array.isArray(m.values)) return true;
    const set = new Set<string>(m.values);
    let v: any;
    try {
      v = getValue ? getValue(params.node) : params.data?.[field];
    } catch {
      v = params.data?.[field];
    }
    const key = v == null || v === '' ? '(빈 값)' : String(v);
    return set.has(key);
  }, [getValue, field]);

  useGridFilter({ doesFilterPass });

  const filteredValues = useMemo(() => {
    if (!search.trim()) return allValues;
    const s = search.toLowerCase();
    return allValues.filter((v) => v.toLowerCase().includes(s));
  }, [allValues, search]);

  const allChecked = filteredValues.length > 0 && filteredValues.every((v) => draft.has(v));
  const someChecked = filteredValues.some((v) => draft.has(v));

  const toggleAll = () => {
    setDraft((prev) => {
      const next = new Set(prev);
      if (allChecked) filteredValues.forEach((v) => next.delete(v));
      else filteredValues.forEach((v) => next.add(v));
      return next;
    });
  };
  const toggle = (v: string) => {
    setDraft((prev) => {
      const next = new Set(prev);
      if (next.has(v)) next.delete(v); else next.add(v);
      return next;
    });
  };

  const apply = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    console.log('[Filter] apply 클릭, draft size=', draft.size, '/', allValues.length, 'onModelChange=', typeof onModelChange);
    try {
      if (draft.size === allValues.length) {
        onModelChange(null);
      } else {
        onModelChange({ values: Array.from(draft) });
      }
      console.log('[Filter] apply OK');
      // 적용 후 팝업 닫기
      setTimeout(() => {
        const evt = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
        document.body.dispatchEvent(evt);
      }, 50);
    } catch (err) {
      console.error('[Filter] apply ERROR', err);
    }
  };
  const cancel = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    console.log('[Filter] cancel 클릭');
    setDraft(new Set(selectedFromModel));
    setSearch('');
    // 팝업 닫기: 그리드 외부 클릭 시뮬레이션
    setTimeout(() => {
      const evt = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
      document.body.dispatchEvent(evt);
    }, 0);
  };
  const reset = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    console.log('[Filter] reset 클릭');
    try {
      setDraft(new Set(allValues));
      setSearch('');
      onModelChange(null);
    } catch (err) {
      console.error('[Filter] reset ERROR', err);
    }
  };

  return (
    <div
      className="p-2 bg-white text-xs"
      style={{ minWidth: 240, width: 240, maxHeight: 400, display: 'flex', flexDirection: 'column' }}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <input
        type="text"
        placeholder="값 검색"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="border rounded px-2 py-1 mb-2 text-xs"
      />
      <label className="flex items-center gap-1 py-1 border-b mb-1 cursor-pointer">
        <input
          type="checkbox"
          checked={allChecked}
          ref={(el) => { if (el) el.indeterminate = !allChecked && someChecked; }}
          onChange={toggleAll}
        />
        <span className="font-semibold">(모두 선택)</span>
        <span className="ml-auto text-gray-400 text-[10px]">
          {draft.size}/{allValues.length}
        </span>
      </label>
      <div style={{ overflowY: 'auto', flex: 1, minHeight: 120 }}>
        {filteredValues.map((v) => (
          <label key={v} className="flex items-center gap-1 py-0.5 cursor-pointer hover:bg-gray-50">
            <input type="checkbox" checked={draft.has(v)} onChange={() => toggle(v)} />
            <span className="truncate" title={v}>{v}</span>
          </label>
        ))}
        {filteredValues.length === 0 && (
          <div className="text-gray-400 py-2 text-center">결과 없음</div>
        )}
      </div>
      <div className="flex gap-1 mt-2 pt-2 border-t">
        <button
          type="button"
          onClick={apply}
          className="flex-1 bg-blue-600 text-white rounded py-1 hover:bg-blue-700"
        >
          확인
        </button>
        <button
          type="button"
          onClick={cancel}
          className="flex-1 bg-gray-200 rounded py-1 hover:bg-gray-300"
        >
          취소
        </button>
        <button
          type="button"
          onClick={reset}
          className="flex-1 bg-gray-100 rounded py-1 hover:bg-gray-200"
        >
          초기화
        </button>
      </div>
    </div>
  );
};

export default CheckboxSetFilter;
