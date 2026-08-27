# Motor de geometria swengine em container (Linux + Python 3.12 + Open3D).
#
# Build:  docker build -t swengine engine/
# Uso:    echo '{"mesh": "/work/scan.ply"}' | docker run -i --rm -v C:\Temp\swengine:/work swengine info
# O diretório montado em /work é onde entram as malhas e saem os resultados.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libgl1 libglx0 libglvnd0 libopengl0 libegl1 \
        libx11-6 libxcb1 libxau6 libxdmcp6 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        open3d trimesh numpy scipy matplotlib rtree pillow networkx build123d

WORKDIR /app
COPY swengine/ /app/swengine/

ENV MPLBACKEND=Agg
VOLUME /work
ENTRYPOINT ["python", "-m", "swengine"]
