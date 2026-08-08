package com.jobiss.conversation;

import org.springframework.stereotype.Component;

import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.Future;

@Component
public class ChatReplyTaskRegistry {

    private final ConcurrentMap<UUID, Future<?>> tasks = new ConcurrentHashMap<>();

    public void register(UUID jobId, Future<?> task) {
        tasks.put(jobId, task);
    }

    public void complete(UUID jobId) {
        tasks.remove(jobId);
    }

    public boolean cancel(UUID jobId) {
        Future<?> task = tasks.remove(jobId);
        return task != null && task.cancel(true);
    }

    public void cancelAll() {
        tasks.forEach((jobId, task) -> task.cancel(true));
        tasks.clear();
    }
}
