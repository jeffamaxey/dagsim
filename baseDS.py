import numpy as np
import scipy.stats as sts
from typing import Union, List
import time
from graphviz import Source
import csv
import pandas as pd
import igraph as ig
from utils.processPlates import get_plate_dot
import copy as cp


# https://graphviz.org/doc/info/attrs.html#d:shape
# https://networkx.org/documentation/stable//reference/drawing.html

class Node:
    def __init__(self, name: str, function, plates=None, observed=True, arguments=None, size_field=None):
        if arguments is None:
            arguments = {}
        self.name = name
        self.parents_dict = {k: v for k, v in arguments.items() if v.__class__.__name__ == "Generic"}
        self.parents = [value for value in self.parents_dict.values()]
        self.additional_parameters = {k: v for k, v in arguments.items() if k not in self.parents_dict}
        self.function = function
        self.output = None
        self.observed = observed
        self.plates = plates
        self.size_field = size_field

    def __str__(self):
        main_str = ""
        main_str += "\tname: " + self.name + "\n"
        main_str += "\ttype: " + self.__class__.__name__ + "\n"
        main_str += "\tfunction: " + self.function.__name__ + "\n"
        # print("->", self.parents)
        main_str += "\targuments: " + str(
            {**{k: v.name for k, v in self.parents_dict.items()}, **self.additional_parameters}) + "\n"
        if self.parents:
            main_str += "\tparents: " + ", ".join([par.name for par in self.parents]) + "\n"
        else:
            main_str += "\tparents: None"
        return main_str

    def forward(self, idx):
        temp_dict = {}
        if self.parents is not None:
            temp_dict = {**temp_dict, **{k: v.output[idx] for k, v in self.parents_dict.items()}}
        temp_dict = {**temp_dict, **self.additional_parameters}
        # print(str(self.name) + str(temp_dict))
        return self.function(**temp_dict)

    def node_simulate(self, num_samples):
        if self.size_field is None:
            self.output = [self.forward(i) for i in range(num_samples)]
        else:
            self.output = self.vectorize_forward(num_samples)

    def vectorize_forward(self, size):
        temp_dict = {self.size_field: size}
        if self.parents is not None:
            temp_dict = {**temp_dict, **{k: v.output for k, v in self.parents_dict.items()}}
        temp_dict = {**temp_dict, **self.additional_parameters}
        # print(str(self.name) + str(temp_dict))
        return self.function(**temp_dict)  # .tolist()

    def __len__(self):
        return len(self.parents)


# class Prior(Node):
#     def __init__(self, name: str, function, arguments=[], plates=None, observed=True):
#         super().__init__(name=name, parents=None, function=function, arguments=arguments,
#                          plates=plates, observed=observed)
#
#     def forward(self):
#         return self.function(*self.arguments)
#
#     def node_simulate(self, num_samples):
#         self.output = [self.forward() for _ in range(num_samples)]


class Generic(Node):
    def __init__(self, name: str, function, arguments=None, plates=None, size_field=None, observed=True):
        super().__init__(name=name, function=function, arguments=arguments,
                         plates=plates, observed=observed, size_field=size_field)

    @staticmethod
    def build_object(**kwargs):
        # check params
        generic = Generic(**kwargs)
        return generic
        # self.unravel = unravel
        # if self.unravel is not None:
        #     print("got here")
        #
        #     def node_simulate(self, num_samples):
        #         print("got in")
        # #         temp_dict = {self.unravel: num_samples}
        # #         # if self.parents is not None:
        # #         #     temp_dict = {k: v.output[idx] for k, v in self.parents_dict.items()}
        # #         temp_dict = {**temp_dict, **self.additional_parameters}
        # #         output = self.function(**self.additional_parameters)
        # #         print("this ",output)
        # #         return output


class Selection(Node):
    def __init__(self, name: str, function, arguments=None):
        super().__init__(name=name, function=function, arguments=arguments)
        if arguments is None:
            arguments = []

    @staticmethod
    def build_object(**kwargs):
        # check params
        selection = Selection(**kwargs)
        return selection

    def filter_output(self, output_dict):
        for key, value in output_dict.items():
            output_dict[key] = [value[i] for i in range(len(value)) if self.output[i]]
        return output_dict


class Stratify(Node):
    def __init__(self, name: str, function, arguments=None):
        super().__init__(name=name, function=function, arguments=arguments)
        if arguments is None:
            arguments = []

    @staticmethod
    def build_object(**kwargs):
        # check params
        stratify = Stratify(**kwargs)
        return stratify

    def filter_output(self, output_dict):
        node_names = output_dict.keys()
        strata = list(set(self.output))
        # A dictionary of dictionaries. Outer dictionary with keys=strata, and inner dictionaries with keys=node_names
        new_dict = {key: {node: [] for node in node_names} for key in strata}

        for i, stratum in enumerate(self.output):
            for k, v in output_dict.items():
                new_dict[stratum][k].append(v[i])

        return new_dict


class Graph:
    def __init__(self, name, list_nodes):
        self.name = name
        self.nodes = list_nodes  # [None] * num_nodes
        self.adj_mat = pd.DataFrame()
        self.plates = self.plate_embedding()
        self.top_order = []
        self.update_topol_order()
        # TODO add build graph where you call the updates once.
        # TODO Add a function to check that no node has a non-Generic node as a parent, as the adj_mat excludes such
        #  nodes.

    def __str__(self):
        main_str = ""
        for idx, node in enumerate(self.nodes):
            main_str += "Node " + str(idx + 1) + ":\n"
            main_str += node.__str__() + "\n"
        return main_str[:-1]

    def plate_embedding(self):
        def get_key_by_label(label):
            for key in plateDict.keys():
                if plateDict[key][0] == label:
                    return key

        plateDict = {0: (None, [])}
        idx = 1
        labels = []
        for node in self.nodes:
            if node.plates:
                for label in node.plates:
                    if label not in labels:
                        plateDict[idx] = (label, [])
                        labels.append(label)
                        idx += 1
                    plateDict[get_key_by_label(label)][1].append(node.name)
            else:
                plateDict[0][1].append(node.name)
        return plateDict

    def add_node(self, node: Union[Generic, Selection, Stratify]):
        if node not in self.nodes:
            self.nodes.append(node)
        # update the topological order whenever a new node is added
        self.update_topol_order()

    def get_selection(self):
        check_for_selection = next((item for item in self.nodes if item.__class__.__name__ == "Selection"), None)
        if check_for_selection is not None:
            return self.nodes.index(check_for_selection)
        else:
            return None

    def get_stratify(self):
        check_for_stratify = next((item for item in self.nodes if item.__class__.__name__ == "Stratify"), None)
        if check_for_stratify is not None:
            return self.nodes.index(check_for_stratify)
        else:
            return None

    def get_node_by_name(self, name: str):
        if not isinstance(name, str):
            # print("Please enter a valid node name")
            return None
        else:
            node = next((item for item in self.nodes if item.name == name), None)
            if node is None:
                print("No node with the name '" + name + "' was found")
            else:
                return node

    def update_adj_mat(self):
        nodes_names = [node.name for node in self.nodes]
        matrix = pd.DataFrame(data=np.zeros([len(self.nodes), len(self.nodes)]), dtype=np.int,
                              columns=nodes_names,
                              index=nodes_names)
        for node in self.nodes:
            if node.parents is not None:
                for parent in node.parents:
                    matrix[node.name][parent.name] = 1
        self.adj_mat = matrix

    def update_topol_order(self):
        self.update_adj_mat()
        G = ig.Graph.Weighted_Adjacency(self.adj_mat.to_numpy().tolist())
        top_order = G.topological_sorting()
        top_order = [list(self.adj_mat.columns)[i] for i in top_order]
        self.top_order = top_order

    def __getitem__(self, item):
        return self.nodes[item]

    def __len__(self):
        return len(self.nodes)

    def generate_dot(self):

        shape_dict = {'Generic': "ellipse", 'Selection': "doublecircle", 'Stratify': "doubleoctagon"}
        dot_str = 'digraph G{\n'
        for child_node in range(len(self)):
            if self[child_node].parents is None:
                my_str = self[child_node].name + " [shape=" + shape_dict['Prior'] + "];\n"
            else:
                my_str = self[child_node].name + " [shape=" + shape_dict[type(self[child_node]).__name__] + "];\n"
            dot_str = dot_str + my_str

        for parent_node in self.adj_mat:
            for child_node in self.adj_mat.loc[parent_node].index:
                if self.adj_mat.loc[parent_node].loc[child_node] == 1:
                    tmp_str = parent_node + "->" + child_node + ";\n"
                    dot_str += tmp_str

        # check if there are any plates defined in the graph
        if len(self.plates) > 1:
            dot_str += get_plate_dot(self.plates)
        dot_str += "}"
        return dot_str

    def draw(self):
        dot_str = self.generate_dot()
        with open(self.name + "_DOT.txt", "w") as file:
            file.write(dot_str)

        s = Source(dot_str, filename=self.name, format="png")
        try:
            s.view(cleanup=True, quiet_view=True)
        except (TypeError, FileNotFoundError):
            from IPython.display import display
            s.render()
            display(Source(dot_str))

    def simulate(self, num_samples, selection=True, stratify=False, csv_name=""):

        def traverse_graph(num_samples):
            output_dict = {}
            for node in self.top_order:
                node = self.get_node_by_name(node)
                node.node_simulate(num_samples)
                if node.__class__.__name__ == "Selection":
                    assert all(isinstance(x, bool) for x in node.output), "The selection node function should return " \
                                                                          "a boolean"
                elif node.__class__.__name__ == "Stratify":
                    assert all(isinstance(x, str) for x in node.output), "The stratification node function should " \
                                                                         "return a string"
                else:
                    # print(str(node.name) + str(type(node.output)))
                    output_dict[node.name] = node.output
            return output_dict

        output_dict = traverse_graph(num_samples)

        selectionNode = self.get_selection()
        if selection:
            if selectionNode is not None:
                output_dict = self.nodes[selectionNode].filter_output(output_dict=output_dict)
                while len(list(output_dict.values())[0]) < num_samples:
                    temp_output = self.nodes[selectionNode].filter_output(output_dict=traverse_graph(1))
                    output_dict = {k: output_dict[k] + temp_output[k] for k in output_dict.keys()}

        stratifyNode = self.get_stratify()
        if stratify:
            if stratifyNode is not None:
                output_dict = self.nodes[stratifyNode].filter_output(output_dict=output_dict)

        if csv_name:
            if stratifyNode is not None:
                for key in output_dict.keys():
                    pd.DataFrame(output_dict[key]).to_csv(csv_name + '_' + key + '.csv', index=False)
            else:
                pd.DataFrame(output_dict).to_csv(csv_name + '.csv', index=False)
        return output_dict

    def ml_simulation(self, num_samples, train_test_ratio, stratify=False, include_external=False, csv_prefix=""):
        if csv_prefix:
            csv_prefix = csv_prefix + "_"
        num_tr_samples = int(num_samples * train_test_ratio)
        num_te_samples = num_samples - num_tr_samples
        train_dict = self.simulate(num_samples=num_tr_samples, stratify=stratify, csv_name=csv_prefix + "train")
        test_dict = self.simulate(num_samples=num_te_samples, stratify=stratify, csv_name=csv_prefix + "test")
        output = [train_dict, test_dict]
        if include_external:
            exter_dict = self.simulate(num_samples=num_te_samples, stratify=stratify, selection=False,
                                       csv_name=csv_prefix + "external")
            output.append(exter_dict)
        return output
