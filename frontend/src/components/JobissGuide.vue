<script setup lang="ts">
defineProps<{ message: string }>();
</script>

<template>
  <div class="guide">
    <img class="guide-character guide-character--jobi" src="/img/jobi-mascot.png" alt="" />
    <p>{{ message }}</p>
  </div>
</template>
