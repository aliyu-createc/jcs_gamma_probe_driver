cmake_minimum_required(VERSION 3.5)
project(jcs_gamma_probe)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  diagnostic_msgs
)

catkin_package()

catkin_install_python(PROGRAMS
  nodes/gamma_probe_node.py
  nodes/dose_web.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/launch
)

install(DIRECTORY web config
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)
