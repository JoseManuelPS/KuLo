#!/usr/bin/env python3
import asyncio
import logging
import sys
from kulo.client import KuloClient
from kulo.models import StreamContext, ContainerInfo

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

async def verify_stream_stops():
    namespace = "demo"
    pod_name = "init-container-pod"
    container_name = "init-setup"

    print(f"Verifying stream stops for {namespace}/{pod_name}/{container_name}...")

    async with KuloClient.create() as client:
        # 1. Get the pod info
        try:
            pods = await client.list_pods(namespace)
            pod = next((p for p in pods if p.name == pod_name), None)
            if not pod:
                print(f"Error: Pod {pod_name} not found. Did you run setup_demo.py?")
                return False
        except Exception as e:
            print(f"Error listing pods: {e}")
            return False

        # 2. Create container info and context
        container = ContainerInfo(
            namespace=namespace,
            pod_name=pod_name,
            container_name=container_name,
            container_type="init"
        )

        context = StreamContext(
            container=container,
            since_seconds=600,
            follow=True,  # IMPORTANT: We want to test follow mode
            tail_lines=10
        )

        # 3. Stream logs and count lines
        line_count = 0
        try:
            # We'll set a timeout to ensure it doesn't run forever if the bug persists
            async with asyncio.timeout(15): 
                async for line in client.stream_logs(context):
                    print(f"Received: {line}")
                    line_count += 1
                    if line_count > 20:
                        print("FAILURE: Received too many lines, likely looping!")
                        return False
            
            print(f"SUCCESS: Stream finished naturally after {line_count} lines.")
            return True

        except asyncio.TimeoutError:
            print("FAILURE: Stream timed out (did not finish in 15s). Likely looping.")
            return False
        except Exception as e:
            print(f"Error during streaming: {e}")
            return False

if __name__ == "__main__":
    success = asyncio.run(verify_stream_stops())
    sys.exit(0 if success else 1)
