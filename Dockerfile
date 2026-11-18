FROM ros:noetic-ros-base

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-ads.txt /tmp/requirements-ads.txt
RUN pip3 install pyserial -r /tmp/requirements-ads.txt

RUN mkdir -p /catkin_ws/src
COPY . /catkin_ws/src/jcs_gamma_probe

WORKDIR /catkin_ws
RUN /bin/bash -c "source /opt/ros/noetic/setup.bash && catkin_make"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["roslaunch", "jcs_gamma_probe", "gamma_probe.launch"]