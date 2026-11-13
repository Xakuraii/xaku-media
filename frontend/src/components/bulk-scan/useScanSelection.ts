import { useCallback, useMemo, useState } from "react";
import type { DiscoveredMediaItem, ScanPost } from "../../../../desktop/shared/types";
import { visibleMedia } from "./utils";

/** Selection is independent from filtering, so users can mix images and videos. */
export function useScanSelection(
  posts: ScanPost[],
  visiblePosts: ScanPost[],
  filter: "all" | "image" | "video" | "album"
) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const visibleItems = useMemo(
    () => visiblePosts.flatMap((post) => visibleMedia(post, filter)),
    [visiblePosts, filter]
  );

  const selectedItems = useMemo<DiscoveredMediaItem[]>(() => {
    if (selected.size === 0) return [];
    return posts
      .flatMap((post) => post.media_items)
      .filter((item) => selected.has(item.id));
  }, [posts, selected]);

  const toggleMedia = useCallback((itemId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }, []);

  const togglePost = useCallback(
    (post: ScanPost) => {
      const ids = post.media_items.map((item) => item.id);
      const allSelected = ids.length > 0 && ids.every((id) => selected.has(id));
      setSelected((prev) => {
        const next = new Set(prev);
        for (const id of ids) {
          if (allSelected) next.delete(id);
          else next.add(id);
        }
        return next;
      });
    },
    [selected]
  );

  const selectVisible = useCallback(
    () => setSelected(new Set(visibleItems.map((item) => item.id))),
    [visibleItems]
  );

  const clearSelection = useCallback(() => setSelected(new Set()), []);

  const selectByType = useCallback(
    (type: "image" | "video") =>
      setSelected(
        new Set(
          posts
            .flatMap((post) => post.media_items)
            .filter((item) => item.media_type === type)
            .map((item) => item.id)
        )
      ),
    [posts]
  );

  const selectAlbums = useCallback(
    () =>
      setSelected(
        new Set(
          posts
            .filter((post) => post.media_items.length > 1)
            .flatMap((post) => post.media_items)
            .map((item) => item.id)
        )
      ),
    [posts]
  );

  const invertSelection = useCallback(
    () =>
      setSelected(
        new Set(
          visibleItems.filter((item) => !selected.has(item.id)).map((item) => item.id)
        )
      ),
    [selected, visibleItems]
  );

  return {
    selected,
    selectedItems,
    visibleItems,
    toggleMedia,
    togglePost,
    selectVisible,
    clearSelection,
    selectByType,
    selectAlbums,
    invertSelection,
  };
}
